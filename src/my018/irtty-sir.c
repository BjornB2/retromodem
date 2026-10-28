/*********************************************************************
 *                
 * Filename:      irtty-sir.c
 * Version:       2.0
 * Description:   IrDA line discipline implementation
 * Status:        Experimental.
 * Author:        Dag Brattli <dagb@cs.uit.no>
 * Created at:    Tue Dec  9 21:18:38 1997
 * Modified at:   Sun Oct 27 22:13:30 2002
 * Modified by:   Martin Diehl <mad@mdiehl.de>
 * Sources:       slip.c by Laurence Culhane,   <loz@holmes.demon.co.uk>
 *                          Fred N. van Kempen, <waltje@uwalt.nl.mugnet.org>
 * 
 *     Copyright (c) 1998-2000 Dag Brattli,
 *     Copyright (c) 2002 Martin Diehl,
 *     All Rights Reserved.
 *      
 *     This program is free software; you can redistribute it and/or 
 *     modify it under the terms of the GNU General Public License as 
 *     published by the Free Software Foundation; either version 2 of 
 *     the License, or (at your option) any later version.
 *  
 *     Neither Dag Brattli nor University of Tromsø admit liability nor
 *     provide warranty for any of this software. This material is 
 *     provided "AS-IS" and at no charge.
 *     
 ********************************************************************/    

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/slab.h>
#include <linux/tty.h>
#include <linux/init.h>
#include <linux/uaccess.h>
#include <linux/delay.h>
#include <linux/mutex.h>
#include <linux/workqueue.h>
#include <linux/gpio.h>
#include <linux/kmod.h>

#include <net/irda/irda.h>
#include <net/irda/irda_device.h>

#include "sir-dev.h"
#include "irtty-sir.h"

static int qos_mtt_bits = 0x03;      /* 5 ms or more */

module_param(qos_mtt_bits, int, 0);
MODULE_PARM_DESC(qos_mtt_bits, "Minimum Turn Time");

/* Optional MY018 selector inputs. Global GPIO numbers are supplied by the
 * adapter setup, which resolves the BCM GPIO controller's current base.
 * This affects only the named UART, preserving USB dongle behaviour.
 */
static char *my018_tty = "ttyAMA0";
static int my018_gpio_a = -1, my018_gpio_b = -1, my018_gpio_c = -1;
module_param(my018_tty, charp, 0444);
module_param(my018_gpio_a, int, 0444);
module_param(my018_gpio_b, int, 0444);
module_param(my018_gpio_c, int, 0444);
static struct gpio my018_selectors[3];
static bool my018_enabled;
/* Experimental, explicitly opt-in: root-owned helper sequences the low-side
 * power switch and UART mux. Never combine with the legacy selector outputs.
 * This callback runs in the sleepable IrDA thread, before changing termios.
 */
static bool my018_power_cycle;
module_param(my018_power_cycle, bool, 0444);
MODULE_PARM_DESC(my018_power_cycle, "Experimental MY018 low-side power-cycle helper");
static unsigned int my018_power_speed;

static int my018_set_speed(struct tty_struct *tty, unsigned int speed)
{
	unsigned int bits;

	if ((!my018_enabled && !my018_power_cycle) || strcmp(tty->name, my018_tty))
		return 0;
	switch (speed) {
	case 9600: bits = 0; break;
	case 19200: bits = 1; break;
	case 38400: bits = 2; break;
	case 57600: bits = 3; break;
	case 115200: bits = 4; break;
	default: return -EINVAL;
	}
	if (my018_power_cycle) {
		char rate[16];
		char *argv[] = { "/usr/bin/timeout", "3",
			"/usr/local/lib/retromodem/my018-power-cycle", rate, NULL };
		static char *envp[] = { "HOME=/", "PATH=/usr/sbin:/usr/bin:/sbin:/bin", NULL };
		int result;

		if (my018_power_speed == speed)
			return 0;
		snprintf(rate, sizeof(rate), "%u", speed);
		result = call_usermodehelper(argv[0], argv, envp, UMH_WAIT_PROC);
		if (result) {
			pr_err("MY018: power-cycle to %u failed: %d\n", speed, result);
			my018_power_speed = 0;
			return result < 0 ? result : -EIO;
		}
		my018_power_speed = speed;
		pr_info("MY018: power-cycled %s to %u bit/s (CBA=%u%u%u)\n",
			tty->name, speed, !!(bits & 4), !!(bits & 2), bits & 1);
		return 0;
	}
	gpio_set_value_cansleep(my018_gpio_a, bits & 1);
	gpio_set_value_cansleep(my018_gpio_b, !!(bits & 2));
	gpio_set_value_cansleep(my018_gpio_c, !!(bits & 4));
	usleep_range(100, 200);
	pr_info("MY018: %s -> %u bit/s (CBA=%u%u%u)\n", tty->name,
		speed, !!(bits & 4), !!(bits & 2), bits & 1);
	return 0;
}

/* ------------------------------------------------------- */

/* device configuration callbacks always invoked with irda-thread context */

/* find out, how many chars we have in buffers below us
 * this is allowed to lie, i.e. return less chars than we
 * actually have. The returned value is used to determine
 * how long the irdathread should wait before doing the
 * real blocking wait_until_sent()
 */

static int irtty_chars_in_buffer(struct sir_dev *dev)
{
	struct sirtty_cb *priv = dev->priv;

	IRDA_ASSERT(priv != NULL, return -1;);
	IRDA_ASSERT(priv->magic == IRTTY_MAGIC, return -1;);

	return tty_chars_in_buffer(priv->tty);
}

/* Wait (sleep) until underlaying hardware finished transmission
 * i.e. hardware buffers are drained
 * this must block and not return before all characters are really sent
 *
 * If the tty sits on top of a 16550A-like uart, there are typically
 * up to 16 bytes in the fifo - f.e. 9600 bps 8N1 needs 16.7 msec
 *
 * With usbserial the uart-fifo is basically replaced by the converter's
 * outgoing endpoint buffer, which can usually hold 64 bytes (at least).
 * With pl2303 it appears we are safe with 60msec here.
 *
 * I really wish all serial drivers would provide
 * correct implementation of wait_until_sent()
 */

#define USBSERIAL_TX_DONE_DELAY	60

static void irtty_wait_until_sent(struct sir_dev *dev)
{
	struct sirtty_cb *priv = dev->priv;
	struct tty_struct *tty;

	IRDA_ASSERT(priv != NULL, return;);
	IRDA_ASSERT(priv->magic == IRTTY_MAGIC, return;);

	tty = priv->tty;
	if (tty->ops->wait_until_sent) {
		tty->ops->wait_until_sent(tty, msecs_to_jiffies(100));
	}
	else {
		msleep(USBSERIAL_TX_DONE_DELAY);
	}
}

/* 
 *  Function irtty_change_speed (dev, speed)
 *
 *    Change the speed of the serial port.
 *
 * This may sleep in set_termios (usbserial driver f.e.) and must
 * not be called from interrupt/timer/tasklet therefore.
 * All such invocations are deferred to kIrDAd now so we can sleep there.
 */

static int irtty_change_speed(struct sir_dev *dev, unsigned speed)
{
	struct sirtty_cb *priv = dev->priv;
	struct tty_struct *tty;
        struct ktermios old_termios;
	int cflag;
	int err;

	IRDA_ASSERT(priv != NULL, return -1;);
	IRDA_ASSERT(priv->magic == IRTTY_MAGIC, return -1;);

	tty = priv->tty;
	err = my018_set_speed(tty, speed);
	if (err)
		return err;

	down_write(&tty->termios_rwsem);
	old_termios = tty->termios;
	cflag = tty->termios.c_cflag;
	tty_encode_baud_rate(tty, speed, speed);
	if (tty->ops->set_termios)
		tty->ops->set_termios(tty, &old_termios);
	priv->io.speed = speed;
	up_write(&tty->termios_rwsem);

	return 0;
}

/*
 * Function irtty_set_dtr_rts (dev, dtr, rts)
 *
 *    This function can be used by dongles etc. to set or reset the status
 *    of the dtr and rts lines
 */

static int irtty_set_dtr_rts(struct sir_dev *dev, int dtr, int rts)
{
	struct sirtty_cb *priv = dev->priv;
	int set = 0;
	int clear = 0;

	IRDA_ASSERT(priv != NULL, return -1;);
	IRDA_ASSERT(priv->magic == IRTTY_MAGIC, return -1;);

	if (rts)
		set |= TIOCM_RTS;
	else
		clear |= TIOCM_RTS;
	if (dtr)
		set |= TIOCM_DTR;
	else
		clear |= TIOCM_DTR;

	/*
	 * We can't use ioctl() because it expects a non-null file structure,
	 * and we don't have that here.
	 * This function is not yet defined for all tty driver, so
	 * let's be careful... Jean II
	 */
	IRDA_ASSERT(priv->tty->ops->tiocmset != NULL, return -1;);
	priv->tty->ops->tiocmset(priv->tty, set, clear);

	return 0;
}

/* ------------------------------------------------------- */

/* called from sir_dev when there is more data to send
 * context is either netdev->hard_xmit or some transmit-completion bh
 * i.e. we are under spinlock here and must not sleep.
 */

static int irtty_do_write(struct sir_dev *dev, const unsigned char *ptr, size_t len)
{
	struct sirtty_cb *priv = dev->priv;
	struct tty_struct *tty;
	int writelen;

	IRDA_ASSERT(priv != NULL, return -1;);
	IRDA_ASSERT(priv->magic == IRTTY_MAGIC, return -1;);

	tty = priv->tty;
	if (!tty->ops->write)
		return 0;
	set_bit(TTY_DO_WRITE_WAKEUP, &tty->flags);
	writelen = tty_write_room(tty);
	if (writelen > len)
		writelen = len;
	return tty->ops->write(tty, ptr, writelen);
}

/* ------------------------------------------------------- */

/* irda line discipline callbacks */

/* 
 *  Function irtty_receive_buf( tty, cp, count)
 *
 *    Handle the 'receiver data ready' interrupt.  This function is called
 *    by the 'tty_io' module in the kernel when a block of IrDA data has
 *    been received, which can now be decapsulated and delivered for
 *    further processing 
 *
 * calling context depends on underlying driver and tty->port->low_latency!
 * for example (low_latency: 1 / 0):
 * serial.c:	uart-interrupt / softint
 * usbserial:	urb-complete-interrupt / softint
 */

static void irtty_receive_buf(struct tty_struct *tty, const u8 *cp,
			      const u8 *fp, size_t count)
{
	struct sir_dev *dev;
	struct sirtty_cb *priv = tty->disc_data;
	int	i;

	IRDA_ASSERT(priv != NULL, return;);
	IRDA_ASSERT(priv->magic == IRTTY_MAGIC, return;);

	if (unlikely(count==0))		/* yes, this happens */
		return;

	dev = priv->dev;
	if (!dev) {
		net_warn_ratelimited("%s(), not ready yet!\n", __func__);
		return;
	}

	for (i = 0; i < count; i++) {
		/* 
		 *  Characters received with a parity error, etc?
		 */
 		if (fp && *fp++) { 
			pr_debug("Framing or parity error!\n");
			sirdev_receive(dev, NULL, 0);	/* notify sir_dev (updating stats) */
			return;
 		}
	}

	sirdev_receive(dev, cp, count);
}

/*
 * Function irtty_write_wakeup (tty)
 *
 *    Called by the driver when there's room for more data.  If we have
 *    more packets to send, we send them here.
 *
 */
static void irtty_tx_work(struct work_struct *work)
{
	struct sirtty_cb *priv = container_of(work, struct sirtty_cb, tx_work);

	sirdev_write_complete(priv->dev);
}

static void irtty_write_wakeup(struct tty_struct *tty) 
{
	struct sirtty_cb *priv = tty->disc_data;

	IRDA_ASSERT(priv != NULL, return;);
	IRDA_ASSERT(priv->magic == IRTTY_MAGIC, return;);

	clear_bit(TTY_DO_WRITE_WAKEUP, &tty->flags);
	if (priv->dev)
		/* PL011 can invoke write_wakeup synchronously from ->write(),
		 * while sir_dev still holds tx_lock. Defer completion until the
		 * UART and sir_dev have released their transmit locks.
		 */
		schedule_work(&priv->tx_work);
}

/* ------------------------------------------------------- */

/*
 * Function irtty_stop_receiver (tty, stop)
 *
 */

static inline void irtty_stop_receiver(struct tty_struct *tty, int stop)
{
	struct ktermios old_termios;
	int cflag;

	down_write(&tty->termios_rwsem);
	old_termios = tty->termios;
	cflag = tty->termios.c_cflag;
	
	if (stop)
		cflag &= ~CREAD;
	else
		cflag |= CREAD;

	tty->termios.c_cflag = cflag;
	if (tty->ops->set_termios)
		tty->ops->set_termios(tty, &old_termios);
	up_write(&tty->termios_rwsem);
}

/*****************************************************************/

/* serialize ldisc open/close with sir_dev */
static DEFINE_MUTEX(irtty_mutex);

/* notifier from sir_dev when irda% device gets opened (ifup) */

static int irtty_start_dev(struct sir_dev *dev)
{
	struct sirtty_cb *priv;
	struct tty_struct *tty;

	/* serialize with ldisc open/close */
	mutex_lock(&irtty_mutex);

	priv = dev->priv;
	if (unlikely(!priv || priv->magic!=IRTTY_MAGIC)) {
		mutex_unlock(&irtty_mutex);
		return -ESTALE;
	}

	tty = priv->tty;

	if (tty->ops->start)
		tty->ops->start(tty);
	/* Make sure we can receive more data */
	irtty_stop_receiver(tty, FALSE);

	mutex_unlock(&irtty_mutex);
	return 0;
}

/* notifier from sir_dev when irda% device gets closed (ifdown) */

static int irtty_stop_dev(struct sir_dev *dev)
{
	struct sirtty_cb *priv;
	struct tty_struct *tty;

	/* serialize with ldisc open/close */
	mutex_lock(&irtty_mutex);

	priv = dev->priv;
	if (unlikely(!priv || priv->magic!=IRTTY_MAGIC)) {
		mutex_unlock(&irtty_mutex);
		return -ESTALE;
	}

	tty = priv->tty;

	/* Make sure we don't receive more data */
	irtty_stop_receiver(tty, TRUE);
	if (tty->ops->stop)
		tty->ops->stop(tty);

	mutex_unlock(&irtty_mutex);

	return 0;
}

/* ------------------------------------------------------- */

static struct sir_driver sir_tty_drv = {
	.owner			= THIS_MODULE,
	.driver_name		= "sir_tty",
	.start_dev		= irtty_start_dev,
	.stop_dev		= irtty_stop_dev,
	.do_write		= irtty_do_write,
	.chars_in_buffer	= irtty_chars_in_buffer,
	.wait_until_sent	= irtty_wait_until_sent,
	.set_speed		= irtty_change_speed,
	.set_dtr_rts		= irtty_set_dtr_rts,
};

/* ------------------------------------------------------- */

/*
 * Function irtty_ioctl (tty, file, cmd, arg)
 *
 *     The Swiss army knife of system calls :-)
 *
 */
static int irtty_ioctl(struct tty_struct *tty,
	unsigned int cmd, unsigned long arg)
{
	struct irtty_info { char name[6]; } info;
	struct sir_dev *dev;
	struct sirtty_cb *priv = tty->disc_data;
	int err = 0;

	IRDA_ASSERT(priv != NULL, return -ENODEV;);
	IRDA_ASSERT(priv->magic == IRTTY_MAGIC, return -EBADR;);

	pr_debug("%s(cmd=0x%X)\n", __func__, cmd);

	dev = priv->dev;
	IRDA_ASSERT(dev != NULL, return -1;);

	switch (cmd) {
	case IRTTY_IOCTDONGLE:
		/* this call blocks for completion */
		err = sirdev_set_dongle(dev, (IRDA_DONGLE) arg);
		break;

	case IRTTY_IOCGET:
		IRDA_ASSERT(dev->netdev != NULL, return -1;);

		memset(&info, 0, sizeof(info)); 
		strncpy(info.name, dev->netdev->name, sizeof(info.name)-1);

		if (copy_to_user((void __user *)arg, &info, sizeof(info)))
			err = -EFAULT;
		break;
	default:
		err = tty_mode_ioctl(tty, cmd, arg);
		break;
	}
	return err;
}


/* 
 *  Function irtty_open(tty)
 *
 *    This function is called by the TTY module when the IrDA line
 *    discipline is called for.  Because we are sure the tty line exists,
 *    we only have to link it to a free IrDA channel.  
 */
static int irtty_open(struct tty_struct *tty) 
{
	struct sir_dev *dev;
	struct sirtty_cb *priv;
	int ret = 0;

	/* Module stuff handled via irda_ldisc.owner - Jean II */
	/* A new attachment may have been reset by prepare-irda. Never trust the
	 * speed cached for a previous attachment when deciding to skip a cycle.
	 */
	if (my018_power_cycle && !strcmp(tty->name, my018_tty))
		my018_power_speed = 0;

	/* stop the underlying  driver */
	irtty_stop_receiver(tty, TRUE);
	if (tty->ops->stop)
		tty->ops->stop(tty);

	tty_driver_flush_buffer(tty);
	
	/* apply mtt override */
	sir_tty_drv.qos_mtt_bits = qos_mtt_bits;

	/* get a sir device instance for this driver */
	dev = sirdev_get_instance(&sir_tty_drv, tty->name);
	if (!dev) {
		ret = -ENODEV;
		goto out;
	}

	/* allocate private device info block */
	priv = kzalloc(sizeof(*priv), GFP_KERNEL);
	if (!priv) {
		ret = -ENOMEM;
		goto out_put;
	}

	priv->magic = IRTTY_MAGIC;
	priv->tty = tty;
	priv->dev = dev;
	INIT_WORK(&priv->tx_work, irtty_tx_work);

	/* serialize with start_dev - in case we were racing with ifup */
	mutex_lock(&irtty_mutex);

	dev->priv = priv;
	tty->disc_data = priv;
	tty->receive_room = 65536;

	mutex_unlock(&irtty_mutex);

	pr_debug("%s - %s: irda line discipline opened\n", __func__, tty->name);

	return 0;

out_put:
	sirdev_put_instance(dev);
out:
	return ret;
}

/* 
 *  Function irtty_close (tty)
 *
 *    Close down a IrDA channel. This means flushing out any pending queues,
 *    and then restoring the TTY line discipline to what it was before it got
 *    hooked to IrDA (which usually is TTY again).  
 */
static void irtty_close(struct tty_struct *tty) 
{
	struct sirtty_cb *priv = tty->disc_data;

	IRDA_ASSERT(priv != NULL, return;);
	IRDA_ASSERT(priv->magic == IRTTY_MAGIC, return;);

	/* Hm, with a dongle attached the dongle driver wants
	 * to close the dongle - which requires the use of
	 * some tty write and/or termios or ioctl operations.
	 * Are we allowed to call those when already requested
	 * to shutdown the ldisc?
	 * If not, we should somehow mark the dev being staled.
	 * Question remains, how to close the dongle in this case...
	 * For now let's assume we are granted to issue tty driver calls
	 * until we return here from the ldisc close. I'm just wondering
	 * how this behaves with hotpluggable serial hardware like
	 * rs232-pcmcia card or usb-serial...
	 *
	 * priv->tty = NULL?;
	 */

	/* we are dead now */
	tty->disc_data = NULL;
	clear_bit(TTY_DO_WRITE_WAKEUP, &tty->flags);
	cancel_work_sync(&priv->tx_work);

	sirdev_put_instance(priv->dev);

	/* Stop tty */
	clear_bit(TTY_DO_WRITE_WAKEUP, &tty->flags);
	if (tty->ops->stop)
		tty->ops->stop(tty);

	kfree(priv);

	pr_debug("%s - %s: irda line discipline closed\n", __func__, tty->name);
}

/* ------------------------------------------------------- */

static struct tty_ldisc_ops irda_ldisc = {
	.num		= N_IRDA,
 	.name		= "irda",
	.open		= irtty_open,
	.close		= irtty_close,
	.read		= NULL,
	.write		= NULL,
	.ioctl		= irtty_ioctl,
 	.poll		= NULL,
	.receive_buf	= irtty_receive_buf,
	.write_wakeup	= irtty_write_wakeup,
	.owner		= THIS_MODULE,
};

/* ------------------------------------------------------- */

static int __init irtty_sir_init(void)
{
	int err;
	int i;
	int numbers[] = { my018_gpio_a, my018_gpio_b, my018_gpio_c };
	const char *labels[] = { "my018-speed-a", "my018-speed-b", "my018-speed-c" };

	if (my018_power_cycle && (numbers[0] >= 0 || numbers[1] >= 0 || numbers[2] >= 0))
		return -EINVAL;

	if (numbers[0] >= 0 || numbers[1] >= 0 || numbers[2] >= 0) {
		for (i = 0; i < 3; i++) {
			if (!gpio_is_valid(numbers[i]))
				return -EINVAL;
			my018_selectors[i].gpio = numbers[i];
			my018_selectors[i].flags = GPIOF_OUT_INIT_LOW;
			my018_selectors[i].label = labels[i];
		}
		for (i = 0; i < 3; i++) {
			err = gpio_request_one(my018_selectors[i].gpio,
				GPIOF_OUT_INIT_LOW, my018_selectors[i].label);
			if (err) {
				while (i-- > 0)
					gpio_free(my018_selectors[i].gpio);
				return err;
			}
		}
		my018_enabled = true;
	}

	if ((err = tty_register_ldisc(&irda_ldisc)) != 0)
		net_err_ratelimited("IrDA: can't register line discipline (err = %d)\n",
				    err);
	if (err && my018_enabled)
		for (i = 0; i < 3; i++)
			gpio_free(my018_selectors[i].gpio);
	return err;
}

static void __exit irtty_sir_cleanup(void) 
{
        tty_unregister_ldisc(&irda_ldisc);
	if (my018_enabled) {
		gpio_set_value_cansleep(my018_gpio_a, 0);
		gpio_set_value_cansleep(my018_gpio_b, 0);
		gpio_set_value_cansleep(my018_gpio_c, 0);
		gpio_free(my018_gpio_a);
		gpio_free(my018_gpio_b);
		gpio_free(my018_gpio_c);
	}
}

module_init(irtty_sir_init);
module_exit(irtty_sir_cleanup);

MODULE_AUTHOR("Dag Brattli <dagb@cs.uit.no>");
MODULE_DESCRIPTION("IrDA TTY device driver");
MODULE_ALIAS_LDISC(N_IRDA);
MODULE_LICENSE("GPL");
